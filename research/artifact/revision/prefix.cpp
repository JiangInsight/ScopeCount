#include "online_engine.hpp"
namespace prefix_admission {
struct Trace{string id;vector<Q> rules;Range range;};
vector<Trace> loadTrace(string path){
    ifstream in(path);string line;getline(in,line);
    vector<Trace> out;
    while(getline(in,line)){
        istringstream row(line);string id;I l,r;U one,zero;if(!(row>>id>>l>>r>>one>>zero))throw runtime_error("invalid trace row");
        if(out.empty()||out.back().id!=id)out.push_back({id,{}, {l,r}});
        if(out.back().range!=Range{l,r})throw runtime_error("one bundle has different ranges");
        out.back().rules.push_back({id,one,zero,{}});
    }
    return out;
}
void replay(string rowfile,string tracefile,string outfile,bool check){
    ifstream in(rowfile,ios::ate|ios::binary);auto length=in.tellg();if(length<=0||U(length)%8)throw runtime_error("invalid rows");
    vector<U>rows(size_t(length)/8);in.seekg(0);in.read((char*)rows.data(),length);Tree tree(rows);
    auto requests=loadTrace(tracefile);History history;vector<bool>previous;Cost rent=0,pureTree=0;
    map<vector<Key>,FixedPlan> plans;
    map<Key,Cost> savings,prices;set<Key> simpleBought;Cost simpleTotal=0,eagerTotal=0;
    ofstream out(outfile);out<<"id\twidth\tbought\tbuys\tbuild_units\tservice_units\tonline_units\toffline_units\ttree_units\teager_units\tscalar_threshold_units\tdesign_ns\n";
    for(auto&request:requests){
        if(request.rules.empty()||request.rules.size()>64)throw invalid_argument("expected 1 to 64 outputs");
        if(request.range.l>request.range.r||request.range.r>rows.size())throw runtime_error("invalid slice");
        vector<Key> keys;for(auto&q:request.rules)keys.emplace_back(q.one,q.zero);
        if(!plans.contains(keys)){auto p=jointProfile(tree,request.rules);plans.emplace(keys,move(p));}
        const auto &p=plans.at(keys);auto start=Clock::now();
        auto i=history.observe(keys,p);auto d=history.solve(i,check);auto timing=elapsed(start);
        int added=0;
        for(size_t j=0;j<d.bought.size();j++){bool before=j<previous.size()&&previous[j];if(before&&!d.bought[j])throw logic_error("lost purchase");added+=(!before&&d.bought[j]);}
        previous=d.bought;
        U simpleKeep=0;
        for(size_t j=0;j<keys.size();j++){
            auto group=find_if(p.cache.begin(),p.cache.end(),[&](auto g){return (g.members>>j)&1;});
            if(group==p.cache.end())throw logic_error("missing price");
            if(prices.emplace(keys[j],group->build).second)eagerTotal+=group->build;
            eagerTotal+=5;
            Cost solo=p.add[j];for(auto [mask,w]:p.ranks)if((mask>>j)&1)solo+=w;
            if(solo>5)savings[keys[j]]+=solo-5;
            if(solo>5&&savings[keys[j]]>=group->build&&simpleBought.insert(keys[j]).second)simpleTotal+=group->build;
            if(!simpleBought.contains(keys[j])||solo<=5)simpleKeep|=U(1)<<j;
        }
        simpleTotal+=History::service(p,simpleKeep);
        rent+=d.service;pureTree+=p.proxy(admission::first_bits(p.b),1);
        if(rent+d.build>2*d.optimum)throw logic_error("competitive ratio violation");
        out<<request.id<<'\t'<<p.b<<'\t'<<count(previous.begin(),previous.end(),true)<<'\t'<<added<<'\t'<<d.build<<'\t'<<d.service<<'\t'<<(rent+d.build)<<'\t'<<d.optimum<<'\t'<<pureTree<<'\t'<<eagerTotal<<'\t'<<simpleTotal<<'\t'<<timing<<'\n';
    }
}
}
int main(int argc,char**argv){try{if(argc<4)throw invalid_argument("prefix rows trace out [check]");prefix_admission::replay(argv[1],argv[2],argv[3],argc>4);return 0;}catch(const exception&e){cerr<<e.what()<<'\n';return 1;}}
