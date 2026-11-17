
#define main unused_scopecount_driver
#include "bundles.cpp"
#undef main

int main(int argc,char** argv){
    try {
        if(argc!=3)throw runtime_error("published_run prefix out.tsv");
        string pre=argv[1];ifstream raw(pre+".rows",ios::binary|ios::ate);
        auto bytes=raw.tellg();if(bytes<=0 || U(bytes)%8 || U(bytes)/8>100000000)throw runtime_error("Bad mask image");
        vector<U> rows(size_t(bytes)/8);raw.seekg(0);
        raw.read(reinterpret_cast<char*>(rows.data()),bytes);if(!raw)throw runtime_error("Short mask image");
        auto start=Clock::now();Tree tree(rows);auto tree_ns=elapsed(start);
        start=Clock::now();Columns cols(rows);auto column_ns=elapsed(start);
        auto all=readq(pre+".queries");
        constexpr int width=6,cycles=3,reps=101;
        if(all.size()!=2*width)throw runtime_error("Expected two six-check workloads");
        ofstream out(argv[2]);if(!out)throw runtime_error("Cannot create log");
        out<<"workload\tmethod\trep\tcompile_ns\texec_ns\tindex_ns\tcount_digest\tranks\tupdates\n";
        for(int group=0;group<2;group++){
            vector<Q> q(all.begin()+group*width,all.begin()+(group+1)*width);
            auto& ranges=q[0].ranges;
            if(ranges.size()!=cycles || ranges[0].l!=0 || ranges.back().r!=rows.size())throw runtime_error("Invalid cycle bounds");
            array<Ans,cycles> truth{};
            for(int i=0;i<cycles;i++){
                auto z=ranges[i];
                if(z.r<=z.l || (i && z.l!=ranges[i-1].r))throw runtime_error("Noncontiguous cycle");
                for(int j=0;j<width;j++){
                    if(q[j].ranges!=ranges)throw runtime_error("Different scope");
                    for(I n=z.l;n<z.r;n++)truth[i][j]+=((rows[n]&q[j].one)==q[j].one) && !(rows[n]&q[j].zero);
                }
            }
            for(int rep=0;rep<reps;rep++)for(int order=0;order<3;order++){
                int method=(rep+order+group)%3;
                start=Clock::now();
                Plan p;vector<Node> cached;
                if(method<2)p=frontier(tree,q,method==1);
                else for(auto& rule:q)cached.push_back(cols.cache(rule));
                auto compile=elapsed(start);
                start=Clock::now();array<Ans,cycles> result{};
                for(int i=0;i<cycles;i++){
                    if(method<2)result[i]=run(tree,p,ranges[i]);
                    else for(int j=0;j<width;j++)result[i][j]=cached[j].count(ranges[i]);
                }
                auto exec=elapsed(start);
                if(result!=truth)throw runtime_error("Native result differs from direct row check");
                U digest=0;for(auto a:result)for(int j=0;j<width;j++)digest=digest*131+U(a[j]);
                auto [r,u]=cost(p);
                out<<(group?"pair":"orphan")<<'\t'<<(method==0?"joint":method==1?"scalar":"cache")<<'\t'
                   <<rep<<'\t'<<compile<<'\t'<<exec<<'\t'<<(method<2?tree_ns:column_ns)<<'\t'<<digest<<'\t'<<r<<'\t'<<u<<'\n';
            }
        }
        return 0;
    }catch(const exception&e){cerr<<e.what()<<'\n';return 1;}
}
